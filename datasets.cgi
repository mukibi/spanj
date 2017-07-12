#!/usr/bin/perl

use strict;
use warnings;
#no warnings 'uninitialized';

#use feature "switch";

use DBI;
use Fcntl qw/:flock SEEK_END/;
#use Storable qw/freeze thaw/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $logd_in = 0;
my $authd = 0;

my $con;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		my $id = $session{"id"};
		if ($id eq "1") {
			$authd++;
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/datasets.cgi">Upload Data</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to upload data.</span> Only the administrator is authorized to take this action.
</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/datasets.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/datasets.cgi">/login.html?cont=/cgi-bin/datasets.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/datasets.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}
	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

my $step = undef;
my $view_dataset = 0;
my $dataset = -1;

if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?step=([0-9]+)\&?/i ) {
		$step = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?act=view_dataset\&?/i ) {
		if ($ENV{"QUERY_STRING"} =~ /\&?dataset=([0-9]+)\&?/i ) {
			$dataset = $1;
			$view_dataset++;	
		}
	}
}

PMP: {
if ($post_mode) {

	if ( not defined $step ) {
		$post_mode = 0;
		$feedback = qq!<p><span style="color: red">Invalid request received.</span>!;
		last PMP;
	}

	if ( $step == 1 ) {

		unless ($multi_part) {
			$post_mode = 0;
			$feedback = qq!<p><span style="color: red">Invalid request received.</span>!;
			last PMP; 
		}

		my $default_line_sep = $/;
		$/ = "\r\n";	

		my $stage = 0;
		my $current_form_var = undef;
		my $current_form_var_content = "";

		my $form_var = 0;
		my $file_var = 0;

		my $file_name = undef;
		my $file_id = undef;
		my $file_ext = undef;

		my $write = 0;
		my $fh = undef;
		my $dir_lock = undef;	

		my $success = 0;
		my $lines = 0;

		#check for the highest id
		#of file uploaded so far.
		my $max_id = -1;
		open ($dir_lock, ">>$upload_dir/.dir_lock");

       		if ($dir_lock) {
        		flock ($dir_lock, LOCK_EX) or print STDERR "Lock error on upload dir_lock: $!$/";

			opendir(my $uploads, "$upload_dir");
			my @files = readdir($uploads);

			F: foreach (@files) {	
				if ($_ =~ /^(\d+)$/) {
					my $f_id = $1;
					$max_id = $f_id if ($f_id > $max_id);
				}
				else {
					next;
				}
			}

			$file_id = $max_id + 1;

			closedir $uploads;
			flock ($dir_lock, LOCK_UN);
                	close $dir_lock;
			$dir_lock = undef;
		}
		else {
			print STDERR "Could not acquire lock for max(file_id) operation.\n";
			$post_mode = 0;
			$feedback = qq!<p><span style="color: red">Error while saving sent file.</span> Maybe you should retry the operation.!;
			last PMP;
		}
	
		my $cntr = 0;
		my $oct_stream = 0;

		while (<STDIN>) {
			if ($_ =~ /$boundary/) {
				if ($form_var) {
					
					if (defined $current_form_var) {
						chomp $current_form_var_content;
						$auth_params{$current_form_var} = $current_form_var_content;
					}

					$current_form_var = undef;
					$current_form_var_content = "";
				}
				elsif ($file_var) {
					if (defined $fh) {
						close $fh;
						$fh = undef;
					}
					if (defined $dir_lock) {
						flock ($dir_lock, LOCK_UN);
                				close $dir_lock;
						$dir_lock = undef;	
					}
				}
				$form_var = 0;
				$file_var = 0;
				$stage = 1;
				$write = 0;	
				next;
			}
			if ($write) {	
				$cntr++;
				if ($form_var) {	
					chomp $_;
					$current_form_var_content .= $_;	
				}

				elsif ($file_var) {
					#introduced this hack to take care of the trailing
					#newline just before the boundary
					#print 1 step behind
					$_ =~ s/\r\n/\n/g;

					#ignore the final blank.
					next if ( $_ eq "\n" );
					print $fh $_;

				}
				next;
			}
			if ($stage == 1) {
				if ($_ =~ /^Content-Disposition:\s*form-data;\s*name="csv_file";\s*filename="([^\"]+)"/) {
					$file_name = htmlspecialchars($1);	
					$file_var = 1;
				}
				elsif ($_ =~ /^Content-Disposition:\s*form-data;\s*name="([^"]+)"/) {	
					$current_form_var = $1;
					$form_var = 1;
				}
				$stage = 2;
				next;
			}
			if ($stage == 2) {
				if ($form_var) {
					if ( $_ eq "\n" or $_ eq "\r\n" ) {
						$write = 1;
					}
				}
				if ($file_var) {
					if ($_ =~ m!^Content-Type:\s*text/(?:(?:plain)|(?:csv))!) {	
						$stage = 3;
					}
					elsif ($_ =~ m!^Content-Type:\s*application/octet-stream!) {
						$stage = 3;
						$oct_stream++;
					}
					else {
						$post_mode = 0;
						$feedback = qq!<p><span style="color: red">Upload failed: the file selected is not a text file.</span> Messeger only accepts data as CSV text files.!;
						last PMP;
					}
				}
				next;
			}
			if ($stage == 3) {
				if ($_ eq "\n" or $_ eq "\r\n") {	
					open ($fh, ">$upload_dir/$file_id") or print STDERR "Could not open uploads dir for writing:$!$/";
			
					$write = 1;
					$success++;	
				}
				next;
			}
		}

		if ($success) {
			if ($oct_stream) {
				unless (-T "$upload_dir/$file_id") {
					$post_mode = 0;	
					$feedback = qq!<p><span style="color: red">Upload failed: the file selected is not a text file.</span> Messeger only accepts data as CSV text files.!;
					last PM;
				}
			}
		}
		else {
			$post_mode = 0;
			$feedback = qq!<span style="color: red">Error saving uploaded file.</span> The data has not been saved.!;
			last PMP;	
		}
	
		unless (exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and ($auth_params{"confirm_code"} eq $session{"confirm_code"})) {
			$feedback = qq!<p><span style="color: red">Invalid request sent.</span> Do not alter the values in the HTML form.!;
				
			#if this request was invalid;
			#delete the uploaded file.
			unlink "$upload_dir/$file_id";

			$post_mode = 0;
			last PMP;
		}


		#now preview data;
		#ask user for any links
		#get foreign key.
		$/ = $default_line_sep;
				
		open (my $f, "<$upload_dir/$file_id");

		my $table = 
qq*
<TABLE border="1">
*;	
	
		my $num_cols = 0;
		my @header_cols = ();

		while (<$f>) {
			chomp;
			$lines++;
			#only want user to preview 1st 10 data rows + header
			next if ($cntr++ > 9);
			my $line = $_;

			my @cols = split/,/,$line;

			KK: for (my $i = 0; $i < (scalar(@cols) - 1); $i++) {
				#escaped
				if ( $cols[$i] =~ /(.*)\\$/ ) {

					my $non_escpd = $1;
					$cols[$i] = $non_escpd . "," . $cols[$i+1];

					splice(@cols, $i+1, 1);
					redo KK;
				}
				#assume that quotes will be employed around
				#an entire field
				#has it been opened?
				if ($cols[$i] =~ /^".+/) {
					#has it been closed? 
					unless ( $cols[$i] =~ /.+"$/ ) {
						#assume that the next column 
						#is a continuation of this one.
						#& that a comma was unduly pruned
						#between them
						$cols[$i] = $cols[$i] . "," . $cols[$i+1];
						splice (@cols, $i+1, 1);
						redo KK;
					}
				}
			}

			for (my $j = 0; $j < @cols; $j++) {
				if ($cols[$j] =~ /^"(.*)"$/) {
					$cols[$j] = $1; 
				}
			}

			$num_cols = scalar(@cols) if (scalar(@cols) > $num_cols);

			if ($lines > 1) {
				$table .= "<TR>";
				for (my $i = 0; $i < @cols; $i++) {
					$table .= "<TD>" . htmlspecialchars($cols[$i]);
				}
			}
			else {
				@header_cols = @cols;

				$table .= "<THEAD><TR>";
				for (my $i = 0; $i < @cols; $i++) {
					$table .= "<TH>" . htmlspecialchars($cols[$i]);
				}
				$table .= "</THEAD>";
				$table .= "<TBODY>";	
			}
		}

		unless ($lines > 0) {
			$post_mode = 0;
			$feedback = qq!<p><span style="color: red">Blank data file uploaded.</span> The file has been disregarded.!;
			unlink "$upload_dir/$file_id";
			last PMP;
		}

		my $preview = "the complete data";

		#does data have more that 10 rows?
		if ($lines > 10) {
			$preview = "a preview of the data";

			my $rem = $lines - 10;
			$table .= qq!<TR><TD colspan="$num_cols" style="text-align: center; border-style: none">.<TR><TD colspan="$num_cols" style="text-align: center; border-style: none">.<TR><TD colspan="$num_cols" style="text-align: center; border-style: none">.<TR><TD style="text-align: center; border-style: none"><a href="/cgi-bin/datasets.cgi?act=view_dataset&dataset=$file_id" target="_blank">$rem more rows</a>!;
		}

		$table .= "</TBODY></TABLE>";

		my $select_field = qq!<SELECT name="foreign_key" id="foreign_key_id">!;
		for (my $i = 0; $i < @header_cols; $i++) {
			if ($i == 0) {
				$select_field .= qq!<OPTION selected value="$i">$header_cols[$i]</OPTION>!;
			}
			else {
				$select_field .= qq!<OPTION value="$i">$header_cols[$i]</OPTION>!;
			}
		}

		$select_field .= "</SELECT>";
	
		my $dataset_header = htmlspecialchars(join('$#$#$', @header_cols));

		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data</title>
<SCRIPT type="text/javascript">

function foreign_key_changed() {

	var selection = document.getElementById("link_to_id").value;

	if (selection == "students") {	
		document.getElementById("foreign_key_name").innerHTML = "the admission number";
	}
	else if (selection == "teachers") {	
		document.getElementById("foreign_key_name").innerHTML = "the teacher id";
	}
	else if (selection == "-") {
		document.getElementById("foreign_key_name").innerHTML = "the unique/primary field";		
	}
}

</SCRIPT>
</head>
<body>
$header
<p><em>You are almost done. Just 1 more step...</em>
<p>Below is $preview you uploaded.
$table
<p>Ensure that this data appears correct. In particular, ensure that the <span style="font-weight: bold">header</span> and <span style="font-weight: bold">number of columns</span> are OK. If they're not, you may need to upload the data again with the changes made.
<p>To be truly useful, a dataset <span style="font-weight: bold">should be linked</span> either to the teachers' database or the students' database. For instance, a dataset linked to the students' database does not have to contain names of students; these will be made available automatically provided the student's admission number is given. Also, every dataset <span style="font-weight: bold">should have a name</span> that describes it as unambigously as possible. For example, instead of naming a dataset <em>'Tour Students'</em>, you can name it 'Form 4 Students Lake Nakuru Tour, Term 2(2014)'</em>.
<p>Every dataset that is not linked to the teachers' or students' database should have a <span style="font-weight: bold">unique/primary</span> field that uniquely identifies each row. A good candidate for this field is a national ID number or a phone number. A name, on the other hand, is a <em>poor</em> choice for a primary field. This will allow you to link each row in the dataset to a specific entry in the list of contacts using this key field.
<FORM method="POST" action="/cgi-bin/datasets.cgi?step=2">

<INPUT type="hidden" name="dataset_id" value="$file_id">
<INPUT type="hidden" name="dataset_filename" value="$file_name">
<INPUT type="hidden" name="header" value="$dataset_header">
<INPUT type="hidden" name="confirm_code" value="$conf_code">

<TABLE>

<TR>
<TD><LABEL for="name">Dataset name</LABEL>
<TD><INPUT type="text" value="" name="dataset_name" size="50" maxlength="100">

<TR>
<TD><LABEL for="link_to">Link dataset to</LABEL>
<TD>

<SELECT name="link_to" id="link_to_id" onchange="foreign_key_changed()">

<OPTION value="students" selected>Students' Database</OPTION>
<OPTION value="teachers">Teachers' Database</OPTION>
<OPTION value="-">Not Linked</OPTION>

</SELECT>

<TR>
<TD><LABEL for="foreign_key" id="foreign_key_label">Which of these fields is <span id="foreign_key_name">the admission number</span>?</LABEL>
<TD>$select_field

<TR>
<TD colspan="2"><INPUT type="submit" name="save" value="Save Dataset">
</TABLE>
</FORM>
</body>
</html>
*;	
	}
	elsif ($step == 2) {

		my $dataset_id = undef;
		my $dataset_filename = undef;
		my $dataset_name = undef;
		my $dataset_header = undef;

		my $link_to = undef;
		my $foreign_key = -1;

		my @errors = ();

		#even had problems?
		#problems of un-confirmed dates?
		unless (exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"}) {
			#these are insufferable
			$feedback = "Some essential hidden values in the HTML form were altered. Please upload your data again.";
			$post_mode = 0;
			last PMP;
		}
		#there be problems of the ID (& those of the ego, & those of the super-ego...)
		if (exists $auth_params{"dataset_id"}) {
			#must be a number
			if ($auth_params{"dataset_id"} =~ /^\d+$/) {

				my $possib_dataset_id = $auth_params{"dataset_id"};

				if (-e "$upload_dir/$possib_dataset_id") {
					$dataset_id = $possib_dataset_id;
				}
				else {
					push @errors, "Unknown dataset id sent.";
				}
			}
			else {
				push @errors, "Invalid dataset id posted. Do not alter the hidden values in the HTML form.";
			}
		}
		else {
			push @errors, "The dataset id was not posted. Do not alter the hidden values in the HTML form.";
		}

		#then there be problems of names
		if (exists $auth_params{"dataset_filename"} and length($auth_params{"dataset_filename"}) > 0) {
			$dataset_filename = $auth_params{"dataset_filename"};
		}
		else {
			push @errors, "The dataset filename was not provided. Do not alter the hidden values in the HTML form.";
		}

		#& more problems of names..
		if (exists $auth_params{"dataset_name"} and length($auth_params{"dataset_name"}) > 0) {
			$dataset_name = $auth_params{"dataset_name"};
		}
		else {
			push @errors, "The dataset name was not provided. Please provide an unambigous name to identify your dataset."
		}

		#& header..
		if (exists $auth_params{"header"} and length($auth_params{"header"}) > 0) {
			$dataset_header = $auth_params{"header"};
		}
		else {
			push @errors, "The dataset header row was not given."
		}

		#but then there're those of links 
		#and those, a man cannot survive.
		if ( exists $auth_params{"link_to"} ) {
			my $possib_link_to = $auth_params{"link_to"};

			if ( $possib_link_to eq "students" or $possib_link_to eq "teachers" or $possib_link_to eq "-" ) {
				$link_to = $possib_link_to;
			}
			else {
				push @errors, "Invalid database link selected. Please select one of the options given.";
			}
		}

		else {
			push @errors, "You did not specify which (if any) database you'd like to link this dataset to. Select one of the options provided.";
		}

		if (defined ($link_to)) {

			my $foreign_key_descr = "teacher id";
			if ($link_to eq "students") {
				$foreign_key_descr = "admission number";
			}
			elsif ($link_to eq "-") {
				$foreign_key_descr = "primary/unique field";
			}

			if (exists $auth_params{"foreign_key"}) {
				my $possib_foreign_key = $auth_params{"foreign_key"};

				if ( $possib_foreign_key =~ /^\d+$/ ) {
					$foreign_key = $possib_foreign_key;
				}
				else {
					push @errors, "Invalid field selected for the $foreign_key_descr. Only select one of the options in the list.";
				}
			}
			else {
				push @errors, "You did not specify which field contains the $foreign_key_descr. Only select one of the options in the list.";
			}
		}
 
		my $error_str = "This error was experienced: $errors[0]" if (@errors);

		if (@errors > 1) {
			$error_str = "The following errors were experienced:<ul>";
			for my $error (@errors) {
				$error_str .= "<li>$error";
			}
			$error_str .= "</ul>";
		}

		#can't recover from a missing
		#id or filename
		if (@errors) { 

			$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data</title>
</head>
<body>

$header

<span style="color: red">Could not save the dataset. </span>$error_str
<p>Would you like to <a href="/cgi-bin/datasets.cgi">upload this file again</a>?

</body>
</html>
*;
			if (defined $dataset_id) {
				#delete this file
				#possible abuse--deleting files through
				#invalid posts.
				#user has to be authd.
				unlink "$upload_dir/$dataset_id";
			}
		}
	
		#valid request
		else {	
			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0}); 
		
			my $prep_stmt0 = $con->prepare("REPLACE INTO datasets VALUES(?,?,?,?,?,?)");
			if ($prep_stmt0) {
				my $rc = $prep_stmt0->execute($dataset_id, $dataset_filename, $dataset_name, $link_to, $foreign_key, $dataset_header);
				if ($rc) {
					$con->commit();

					$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data</title>
</head>
<body>

$header
<p><em>Your dataset has been saved!</em> You should now be able to use it.
</body>
</html>
*;
					#log action
					my @today = localtime;	
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

       					if ($log_f) {	
       						@today = localtime;	
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock ($log_f, LOCK_EX) or print STDERR "Could not log upload dataset for 1 due to flock error: $!$/";
						seek ($log_f, 0, SEEK_END);
				 
						print $log_f "1 UPLOAD DATASET $time\n";
						flock ($log_f, LOCK_UN);
       						close $log_f;
       					}
					else {
						print STDERR "Could not log upload dataset for 1: $!\n";
					}

				}
				else {
					print STDERR "Could not execute INSERT INTO datasets statement: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare INSERT INTO datasets: ", $con->errstr,$/;  
			}	
		}
	}
}
}
#why did I not else {}
#to allow GOTOs
if (not $post_mode) {

	if ($view_dataset) {
		if ( -e "$upload_dir/$dataset" ) {

			open (my $f, "$upload_dir/$dataset");

			
			if ($f) {
				my $table = 
qq*
<TABLE border="1">
*;
				my $num_cols = 0;
				my @header_cols = ();
				my $lines = 0;

				while (<$f>) {
					chomp;
					$lines++;
					#only want user to preview 1st 10 data rows + header
					
					my $line = $_;

					my @cols = split/,/,$line;

					JJ: for (my $i = 0; $i < (scalar(@cols) - 1); $i++) {
						#escaped
						if ( $cols[$i] =~ /(.*)\\$/ ) {
	
							my $non_escpd = $1;
							$cols[$i] = $non_escpd . "," . $cols[$i+1];
		
							splice(@cols, $i+1, 1);
							redo JJ;
						}
						#assume that brackets will be employed around
						#an entire field
						#has it been opened?
						if ($cols[$i] =~ /^".+/) {
							#has it been closed? 
							unless ( $cols[$i] =~ /.+"$/ ) {
								#assume that the next column 
								#is a continuation of this one.
								#& that a comma was unduly pruned
								#between them
								$cols[$i] = $cols[$i] . "," . $cols[$i+1];
								splice (@cols, $i+1, 1);
								redo JJ;
							}
						}
					}
		
					#clear quotes
					for (my $j = 0; $j < @cols; $j++) {
						if ($cols[$j] =~ /^"(.*)"$/) {
							$cols[$j] = $1; 
						}
					}

					$num_cols = scalar(@cols) if (scalar(@cols) > $num_cols);

					if ($lines > 1) {
						$table .= "<TR>";
						for (my $i = 0; $i < @cols; $i++) {
							$table .= "<TD>" . htmlspecialchars($cols[$i]);
						}
					}
					else {
						$table .= "<THEAD><TR>";
						for (my $i = 0; $i < @cols; $i++) {
							$table .= "<TH>" . htmlspecialchars($cols[$i]);
						}
						$table .= "</THEAD>";
						$table .= "<TBODY>";	
					}
				}
	
				$table .= "</TBODY></TABLE>";
				$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data - View Dataset</title>
</head>
<body>

$header
<p>

$table

</body>
</html>
*;
			}
		}
		else {
			$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data - View Dataset</title>
</head>
<body>

$header
<p>
<span style="color: red">The requested dataset does not exist.</span>
*;

		}
	}
	else 	{

		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		$content = qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data</title>
</head>
<body>
$header
$feedback
<p>Messenger accepts data in the form of CSV (Comma-Separated Values) files. Ensure the data has a <span style="font-weight: bold">header</span>, that the <span style="font-weight: bold">field delimeter</span> is a comma(,) and the <span style="font-weight: bold">text delimiter</span> (if one is necessary) is double quotation marks/inverted commas("").
<p>Most common spreadsheet programs allow you to conveniently save your data as CSV files.  Click on <span style="font-weight: bold">'Save As'</span> (if this is available in your spreadsheet program) and see if Text/CSV is one of the supported formats. Alternatively, check if an <span style="font-weight: bold">'Export'</span> to CSV function is provided. If you've been successful so far, verify that the correct delimeter is used (,) and that 'fixed-width columns' is NOT selected.
<p>If your CSV file is ready, you're ready to go. 
<p>
<FORM method="POST" action="/cgi-bin/datasets.cgi?step=1" enctype="multipart/form-data">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<TABLE>
<TR>
<TD><LABEL for="csv_file">CSV file</LABEL>
<TD><INPUT type="file" name="csv_file">
<TR>
<TD colspan="2"><INPUT type="submit" name="upload" value="Upload File">
</TABLE>
</FORM>

</body>
</html>
*;

	}
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

