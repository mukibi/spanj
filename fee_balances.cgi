#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

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
		$id = $session{"id"};
		#only bursar(user 2) and accountant(mod 17) can view fee balances
		if ($id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/fee_balances.cgi">Fee Balances</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to view fee balances.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Prepare Fee Balances</title>
</head>
<body>
$header

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
		print "Location: /login.html?cont=/cgi-bin/fee_balances.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/fee_balances.cgi">/login.html?cont=/cgi-bin/fee_balances.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/fee_balances.cgi">Click Here</a> 
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
PM: {
if ($post_mode) {

	unless ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid request.</span> Do not alter the hidden values in the HTML form.!;
		$post_mode = 0;
		last PM; 
	}

	my $adm_filtered = 0;
	my %adms = ();	

	if (exists $auth_params{"adm_nos"} and length($auth_params{"adm_nos"}) > 0) {
		
		my @possib_adms = split/\s+/,$auth_params{"adm_nos"};

		for my $possib_adm (@possib_adms) {

			if ($possib_adm =~ /^\d+$/) {
				$adms{$possib_adm} = {};
				$adm_filtered++;	
			}

			#ranges
			elsif ($possib_adm =~ /^(\d+)\-(\d+)$/) {
				my $start = $1;
				my $stop = $2;
				
				#be kind to users, swap start 
				#and stop if reverse-ordered
				if ( $start > $stop ) {
					my $tmp = $start;
					$start = $stop;
					$stop = $tmp; 
				}

				for ( my $i = $start; $i <= $stop; $i++ ) {
					$adms{$i} = {};
					$adm_filtered++;	
				}
			}
		}

		#read 'adms' table to determine student rolls
		my %rolls = ();
		my $prep_stmt3 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE adm_no=? LIMIT 1");

		if ($prep_stmt3) {

			for my $adm (keys %adms) {

				my $rc = $prep_stmt3->execute($adm);

				if ($rc) {
					while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
						${$adms{$rslts[0]}}{"roll"} = $rslts[1];
						$rolls{$rslts[1]} = "N/A";		
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM adms statement: ", $prep_stmt3->errstr, $/;
				}
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM adms statement: ", $prep_stmt3->errstr, $/;
		}

		for my $adm (keys %adms) {
			delete $adms{$adm} if (not exists ${$adms{$adm}}{"roll"});
		}

		#read 'student_rolls' to derermine classes
		if ( scalar (keys %rolls) > 0 ) {

			my %roll_students_lookup = ();
			my $yr = (localtime)[5] + 1900;

			my @where_clause_bts = ();
	
			for my $roll (keys %rolls) {
				push @where_clause_bts, "table_name=?";
			}

			my $where_clause = join(" OR ", @where_clause_bts);

			my $prep_stmt4 = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls WHERE $where_clause");

			if ($prep_stmt4) {
				my $rc = $prep_stmt4->execute(keys %rolls);
				if ($rc) {
					while ( my @rslts = $prep_stmt4->fetchrow_array() ) {	
						my $class = "N/A";
						#student ha already graduated
						if ( $rslts[3] < $yr ) {

							my $study_yr = ($rslts[3] - $rslts[2]) + 1;
							$class = uc($rslts[1]);
							$class =~ s/\d+/$study_yr/;

							$class .= "($rslts[3])";	
						}
						else {
							my $study_yr = ($yr - $rslts[2]) + 1;
							$class = uc($rslts[1]);
							$class =~ s/\d+/$study_yr/;	
						}

						$rolls{$rslts[0]} = $class;
						
						#print "X-Debug-1-$rslts[0]: $class\r\n";
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt4->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt4->errstr, $/;
			}

			for my $adm ( keys %adms ) {

				my $roll = ${$adms{$adm}}{"roll"};
				my $class = "N/A";

				#accomodate missing classes
				if ( exists $rolls{$roll} ) {
					$class = $rolls{$roll};
				}

				${$adms{$adm}}{"class"} = $class;
				${$roll_students_lookup{$roll}}{$adm}++;
			}

			for my $roll ( keys %rolls ) {

				my @roll_students =  keys %{$roll_students_lookup{$roll}};
				my $num_roll_students = scalar(@roll_students);

				my @where_clause_bts = ();
	
				foreach ( @roll_students ) {
					push @where_clause_bts, "adm=?";
				}

				my $where_clause = join(" OR ", @where_clause_bts);

				my $prep_stmt5 = $con->prepare("SELECT adm,s_name,o_names,house_dorm FROM `$roll` WHERE $where_clause LIMIT $num_roll_students");

				if ( $prep_stmt5 ) {

					my $rc = $prep_stmt5->execute(@roll_students);

					if ($rc) {
						while ( my @rslts = $prep_stmt5->fetchrow_array() ) {
							${$adms{$rslts[0]}}{"name"} = $rslts[1] . " " .$rslts[2];
							${$adms{$rslts[0]}}{"dorm"} = (not defined $rslts[3] or $rslts[3] eq "") ? "N/A" : $rslts[3];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM $roll statement: ", $prep_stmt5->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt5->errstr, $/;
				}

			}
		}
	}

	my $class_filtered = 0;
	my %classes;
	my %student_rolls = ();
	
	#don't do adm AND class lim
	if (not $adm_filtered) {

		my $yr = (localtime)[5] + 1900;
		if ( exists $auth_params{"year"} and $auth_params{"year"} =~ /^\d{4}$/ ) {
			#can't go forward in time
			if ($auth_params{"year"} <= $yr) {
				$yr = $auth_params{"year"};	
			}
		}

		for my $auth_param (keys %auth_params) {
			if ($auth_param =~ /^class_/) {
				$classes{uc($auth_params{$auth_param})}++;	
			}
		}

		#read student rolls
		if ( scalar(keys %classes) > 0 ) {
			$class_filtered++;

			my $current_yr = (localtime)[5] + 1900;

			my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls");
	
			if ($prep_stmt1) {
				my $rc = $prep_stmt1->execute();
				if ($rc) {
					while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

						my $class = "N/A";
						#student ha already graduated
						if ( $rslts[3] < $current_yr ) {

							my $study_yr = ($yr - $rslts[2]) + 1;
							$class = uc($rslts[1]);
							$class =~ s/\d+/$study_yr/;

							if (exists $classes{$class}) {
								$student_rolls{$rslts[0]} = $class . "($rslts[3])" ;
							}
						}
						else {
							my $study_yr = ($yr - $rslts[2]) + 1;
							$class = uc($rslts[1]);
							$class =~ s/\d+/$study_yr/;	
							if (exists $classes{$class}) {
								$student_rolls{$rslts[0]} = $class;
							}
						}
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
			}
		}

		if ( scalar (keys %student_rolls) ) {
			for my $roll ( keys %student_rolls ) {

				my $class = $student_rolls{$roll};

				my $prep_stmt2 = $con->prepare("SELECT adm,s_name,o_names,house_dorm FROM `$roll`");

				if ($prep_stmt2) {
					my $rc = $prep_stmt2->execute();
					if ($rc) {
						while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
							$adms{$rslts[0]} = {"class" => $class,"name" => $rslts[1] . " " .$rslts[2], "dorm" => ((not defined $rslts[3] or $rslts[3] eq "") ? "N/A" : $rslts[3])};
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM $roll statement: ", $prep_stmt2->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt2->errstr, $/;
				}
			}
		}
	}

	#no student matched
	unless ( scalar(keys %adms) > 0 ) {
		#an invalid selection was made
		if ($adm_filtered or $class_filtered) {
			$feedback = qq!<span style="color: red">Your student filter did not match any students in the database.</span>!;
		}
		else {
			$feedback = qq!<span style="color: red">You did not specify any student filter(admission number or class).</span>!;
		}
		$post_mode = 0;
		last PM;
	}

	my ($min,$max) = (undef, undef);

	if (exists $auth_params{"balance_expr"} and $auth_params{"balance_expr"} ne "") {
		my $balance_expr = $auth_params{"balance_expr"};
		if ( $balance_expr =~ /^([><])\s*(\d+)$/ ) {
			my $symbol = $1;
			my $limit = $2;
			if ($symbol eq "<") {
				$max = $limit;
			}
			else {
				$min = $limit;
			}
		}

		else {
			$feedback = qq!<span style="color: red">Invalid balance filter.</span>!;
			$post_mode = 0;
			last PM;
		}
	} 

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;
	my %voteheads = ("arrears" => "Arrears");

	#read fee structure -- for relevant voteheads
	my $prep_stmt6 = $con->prepare("SELECT votehead_index,votehead_name,class,amount,hmac FROM fee_structure");
	
	if ($prep_stmt6) {
	
		my $rc = $prep_stmt6->execute();
		if ($rc) {
			while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
						
				my $decrypted_votehead_index = $cipher->decrypt($rslts[0]);
				my $decrypted_votehead_name = $cipher->decrypt($rslts[1]);
				my $decrypted_class = $cipher->decrypt($rslts[2]);
				my $decrypted_amount = $cipher->decrypt($rslts[3]);

				my $votehead_index = remove_padding($decrypted_votehead_index);
				my $votehead_name = remove_padding($decrypted_votehead_name);
				my $class = remove_padding($decrypted_class);
				my $amount = remove_padding($decrypted_amount);
	
				#valid decryption
				if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($votehead_index . $votehead_name . $class . $amount, $key));
								
					#auth the data
					if ( $hmac eq $rslts[4] ) {	
						$voteheads{lc($votehead_name)} = $votehead_name;
					}
				}

			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM fee_structure: ", $prep_stmt6->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM fee_structure: ", $prep_stmt6->errstr, $/;
	}

	my %stud_balances = ();

	#arrears
	my @where_clause_bts = ();#("BINARY account_name=?");

	foreach ( keys %voteheads ) {
		push @where_clause_bts, "BINARY account_name=?";
	}

	my $where_clause = join(" OR ", @where_clause_bts);
	my $max_num_rows = scalar(@where_clause_bts);

	my $prep_stmt7 = $con->prepare("SELECT account_name,class,amount,hmac FROM account_balances WHERE $where_clause LIMIT $max_num_rows");
	
	if ($prep_stmt7) {

		for my $adm (keys %adms) {

			my %encd_accnt_names = ();

			#$encd_accnt_names{$cipher->encrypt(add_padding($adm . "-" . "arrears"))} = "arrears";

			for my $votehead (keys %voteheads) {
				$encd_accnt_names{$cipher->encrypt(add_padding($adm . "-" . $votehead))} = $votehead;
			}

			my $rc = $prep_stmt7->execute(keys %encd_accnt_names);

			if ($rc) {
				while (my @rslts = $prep_stmt7->fetchrow_array()) {

					my $decrypted_account_name = $cipher->decrypt($rslts[0]);
					my $decrypted_class = $cipher->decrypt($rslts[1]);
					my $decrypted_amount = $cipher->decrypt($rslts[2]);

					my $account_name = remove_padding($decrypted_account_name);
					my $class = remove_padding($decrypted_class);
					my $amount = remove_padding($decrypted_amount);

					#valid decryption
					if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

						my $hmac = uc(hmac_sha1_hex($account_name . $class . $amount, $key));

						#auth the data
						if ( $hmac eq $rslts[3] ) {
							my $votehead = $encd_accnt_names{$rslts[0]};
							${$stud_balances{$adm}}{$votehead} = $amount;
						}
					}
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM account_balances: ", $prep_stmt7->errstr, $/;
			}
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM account_balances: ", $prep_stmt7->errstr, $/;
	}

	#process balance expression
	if (defined $max or defined $min) {

		for my $adm (keys %adms) {

			my $total = 0;

			if (exists $stud_balances{$adm}) {
				foreach ( keys %{$stud_balances{$adm}} ) {
					$total += ${$stud_balances{$adm}}{$_};
				}
			}

			#<$max
			if (defined $max) {
				unless ($total < $max) {
					delete $adms{$adm};
				}
			}
			#>min
			else {
				unless ($total > $min) {
					delete $adms{$adm};
				}
			}
		}
	}

	#view for printing
	if ( exists $auth_params{"view_print"} and $auth_params{"view_print"} eq "View/Print" ) {

		my $template = $auth_params{"message_format"};

		my $results = "";
		for my $adm (sort { $a <=> $b } keys %adms) {

			my $stud_data = htmlspecialchars($template);	
	
			#newlines
			$stud_data =~ s/\r?\n/<br>/g;

			#allow bold, italics, underline, <<letter_head>>, <<
			$stud_data =~ s/&#60;b&#62;/<span style="font-weight: bold">/ig;
			$stud_data =~ s/&#60;\/b&#62;/<\/span>/ig;
			
			$stud_data =~ s/&#60;u&#62;/<span style="text-decoration: underline">/ig;
			$stud_data =~ s/&#60;\/u&#62;/<\/span>/ig;

			$stud_data =~ s/&#60;i&#62;/<span style="font-style: italic">/ig;
			$stud_data =~ s/&#60;\/i&#62;/<\/span>/ig;

			#letterhead
			if ( $stud_data =~ /&#60;&#60;letter_head&#62;&#62;/g ) {
				$stud_data =~ s!&#60;&#60;letter_head&#62;&#62;!<p><img src="/images/letterhead2.png" alt="" href="/images/letterhead2.png" style="padding: 0px 0px 0px 0px; margin: 0px 0px 0px 0px">!g;
			}

			#student details
			my $stud_details = 
qq!
<TABLE style="align: left">
<TR><TH>Adm No.:<TD>$adm
<TR><TH>Name:<TD>${$adms{$adm}}{"name"}
<TR><TH>Class:<TD>${$adms{$adm}}{"class"}
<TR><TH>Dorm/House:<TD>${$adms{$adm}}{"dorm"}
</TABLE>
!;

			$stud_data =~ s/&#60;&#60;student_details&#62;&#62;/$stud_details/g;
		
			my $fee_balance = 
qq!
<TABLE border="1" style="width: 80mm">
<THEAD><TH>Votehead<TH>Amount</THEAD>
<TBODY>
!;
			my $total = 0;
			for my $votehead (sort {$a cmp $b} keys %voteheads) {
				my $amount = 0;	
				if ( exists ${$stud_balances{$adm}}{$votehead} ) {
					$total += ${$stud_balances{$adm}}{$votehead};
					$amount = format_currency(${$stud_balances{$adm}}{$votehead});
				}	
				$fee_balance .= qq!<TR><TD style="align: left">$voteheads{$votehead}<TD style="align: right">$amount!; 
			}

			my $total_formatted = format_currency($total);

			$fee_balance .= qq!<TR><TD style="align: left">Total<TD style="align: right">$total_formatted!;
			$fee_balance .= "</TBODY></TABLE>";

			$stud_data =~ s/&#60;&#60;fee_balance&#62;&#62;/$fee_balance/g;

			$results .= qq!<p>$stud_data<br class="new_page">!;
		}

		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Fee Balances</title>

<STYLE type="text/css">

\@media print {
	body {
		margin-top: 0px;
		margin-bottom: 0px;
		padding: 0px;
		font-size: 10pt;
		font-family: "Times New Roman", serif;	
	}

	div.no_header {
		display: none;
	}

	br.new_page {
		page-break-after: always;
	}

}

\@media screen {
	div.noheader {}	
	br.new_page {}
}

</STYLE>
</head>
<body>
<div class="no_header">
$header
</div>
$results
</body>
</html>
*;

		#log view
		my @today = localtime;	
		my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

		open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
       		if ($log_f) {

			my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
			flock ($log_f, LOCK_EX) or print STDERR "Could not log view balances for $id due to flock error: $!$/";
			seek ($log_f, 0, SEEK_END);	
 
			print $log_f "$id VIEW BALANCES $time\n";
			flock ($log_f, LOCK_UN);
               		close $log_f;
        	}
		else {
			print STDERR "Could not log view balances $id: $!\n";
		}
	}
	#download as spreadsheet
	else {
		use Spreadsheet::WriteExcel;
		use Spreadsheet::WriteExcel::Utility;
		use Digest::SHA qw/sha1_hex/;

		#filename is the SHA 1 of adms
		my $adms_slurp = join("", sort {$a <=> $b} keys %adms);
		my $f_name = sha1_hex($adms_slurp);

		my ($workbook,$worksheet,$bold,$rotated,$default_props,$spreadsheet_name, $row,$col) = (undef,undef,undef,undef,undef,0,0);	

		$workbook = Spreadsheet::WriteExcel->new("${doc_root}/accounts/balances/$f_name.xls");

		if (defined $workbook) {

			$bold = $workbook->add_format( ("bold" => 1, "size" => 12) );
			$rotated = $workbook->add_format( ("bold" => 1, "size" => 14, "align" => "left", "rotation"=>"90") );

			$default_props = $workbook->add_format( ("size" => 12) );
			
			$workbook->set_properties( ("title" => "Fee balances", "comments" => "lecxEetirW::teehsdaerpS htiw detaerC; User: $id") );
			$worksheet = $workbook->add_worksheet();
			$worksheet->set_landscape();
			$worksheet->hide_gridlines(0);

			$worksheet->write_string($row, $col++, "Adm No.", $rotated);
			$worksheet->write_string($row, $col++, "Name", $rotated);
			$worksheet->write_string($row, $col++, "Class", $rotated);
			$worksheet->write_string($row, $col++, "House/Dorm", $rotated);

			for my $votehead ( sort {$a cmp $b} keys %voteheads ) {
				$worksheet->write_string($row, $col++, $voteheads{$votehead}, $rotated);
			}

			$worksheet->write_string($row, $col++, "Total", $rotated);

			my %votehead_totals = ();
			my $total_total = 0;

			for my $adm (sort { $a <=> $b } keys %adms) {
				$row++;
				$col = 0;
				$worksheet->write_number($row, $col++, $adm, $default_props);

				$worksheet->write_string($row, $col++, ${$adms{$adm}}{"name"}, $default_props);
				$worksheet->write_string($row, $col++, ${$adms{$adm}}{"class"}, $default_props);
				$worksheet->write_string($row, $col++, ${$adms{$adm}}{"dorm"}, $default_props);

				my $total = 0;

				for my $votehead (sort {$a cmp $b} keys %voteheads) {
					my $amount = 0;	
					if ( exists ${$stud_balances{$adm}}{$votehead} ) {	
						$amount = ${$stud_balances{$adm}}{$votehead};
						$total += $amount;
					}
					$votehead_totals{$votehead} += $amount;
					
					$worksheet->write_number($row, $col++, $amount, $default_props);
				}

				$total_total += $total;

				my $total_start = xl_rowcol_to_cell($row, 4);
				my $total_end = xl_rowcol_to_cell($row, $col-1);

				$worksheet->write_formula($row, $col++, "=SUM($total_start:$total_end)", $bold, $total);	
			}

			$row++;
			$col = 0;

			$worksheet->write_blank($row, $col++, $bold);
			$worksheet->write_blank($row, $col++, $bold);
			$worksheet->write_blank($row, $col++, $bold);
			$worksheet->write_blank($row, $col++, $bold);

			for my $votehead ( sort {$a cmp $b} keys %votehead_totals ) {

				my $votehead_start = xl_rowcol_to_cell(1, $col);
				  my $votehead_end = xl_rowcol_to_cell($row - 1, $col);	

				$worksheet->write_formula($row, $col++, "=SUM($votehead_start:$votehead_end)", $bold, $votehead_totals{$votehead});
			}

			my $total_total_start = xl_rowcol_to_cell(1, $col);
			  my $total_total_end = xl_rowcol_to_cell($row - 1, $col);

			$worksheet->write_formula($row, $col++, "=SUM($total_total_start:$total_total_end)", $bold, $total_total);


			$workbook->close();

			print "Status: 302 Moved Temporarily\r\n";
			print "Location: /accounts/balances/$f_name.xls\r\n";
			print "Content-Type: text/html; charset=UTF-8\r\n";

   			my $content = 
qq{
<html>
<head>
<title>Spanj: Accounts Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/accounts/balances/$f_name.xls">/accounts/balances/$f_name.xls</a>. If you were not, <a href="/accounts/balances/$f_name.xls">Click here</a> 
</body>
</html>
};

			my $content_len = length($content);	
			print "Content-Length: $content_len\r\n";
			print "\r\n";
			print $content;
			if ($con) {
				$con->disconnect();
			}

			#log download
			my @today = localtime;	
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
      	 		if ($log_f) {

				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock ($log_f, LOCK_EX) or print STDERR "Could not log download balances for $id due to flock error: $!$/";
				seek ($log_f, 0, SEEK_END);	
 
				print $log_f "$id DOWNLOAD BALANCES $time\n";
				flock ($log_f, LOCK_UN);
               			close $log_f;
      		  	}
			else {
				print STDERR "Could not log view balances $id: $!\n";
			}

			exit 0;
		}
		else {
			print STDERR "Could not create workbook: $!$/";	
		}	
	}	
}
}

if ( not $post_mode) {

	my %grouped_classes = ("1"=> "1", "2"=> "2", "3"=> "3","4"=> "4");
	
	my $prep_stmt = $con->prepare("SELECT value FROM vars WHERE id='1-classes' LIMIT 1");

	if ($prep_stmt) {
		my $rc = $prep_stmt->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt->fetchrow_array()) {
				my @classes = split/,/, $rslts[0];
				%grouped_classes = ();
				for my $class (@classes) {
					if ($class =~ /(\d+)/) {	
						$grouped_classes{$1}->{$class}++;
					}
				}
			}
		}
	}

	my $classes_select = qq!<TABLE cellpadding="5%" cellspacing="5%"><TR>!;
	for my $class_yr (sort {$a <=> $b} keys %grouped_classes) {
		my @classes = keys %{$grouped_classes{$class_yr}};
		
		$classes_select .= "<TD>";
		for my $class (sort {$a cmp $b} @classes) {
			$classes_select .= qq{<INPUT type="checkbox" name="class_$class" value="$class"><LABEL for="class_$class">$class</LABEL><BR>};
		}
	}

	my $current_yr = (localtime)[5] + 1900; 
	$classes_select .= qq!<TD style="vertical-align: center; border-left: solid"><LABEL for="year">Year</LABEL>&nbsp;<INPUT type="text" size="4" maxlength="4" name="year" value="$current_yr"></TABLE>!;

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Fee Balances</title>

<script type="text/javascript">

var balance_expr_re = /^[><]?\\s\*[0-9]\*\$/;
var adm_no_re = /^([0-9]\*(\\-[0-9]\*)?\\s\*)\*\$/;

function check_adm_nos() {

	var adm_numbers = document.getElementById("adm_nos").value;
	if (adm_numbers.match(adm_no_re)) {
		document.getElementById("adm_nos_err").innerHTML = "";
	}
	else {
		document.getElementById("adm_nos_err").innerHTML = "\*";
	}
}

function check_balance_expr() {
	var expr = document.getElementById("balance_expr").value;
	if (expr.match(balance_expr_re)) {
		document.getElementById("balance_expr_err").innerHTML = "";
	}
	else {
		document.getElementById("balance_expr_err").innerHTML = "\*";
	}
}

</script>
</head>
<body>
$header
$feedback
<form method="POST" action="/cgi-bin/fee_balances.cgi">
<input type="hidden" name="confirm_code" value="$conf_code">
<p><h3>Filter Students By</h3>

<ul style="list-style-type: none">
<li><h4>Adm No.</h4>
<span id="adm_nos_err" style="color: red"></span><label for="adm_no">Adm no(s)</label>&nbsp;<input type="text" size="50" name="adm_nos" id="adm_nos" onkeyup="check_adm_nos()">&nbsp;&nbsp;<em>You can include ranges like 4490-4500</em>
<li><h4>Class</h4>
$classes_select
<li><h4>Balance</h4>
<span id="balance_expr_err" style="color: red"></span><label for="balance_expr">Balance</label>&nbsp;&nbsp;<input type="text" size="20" name="balance_expr" id="balance_expr" onkeyup="check_balance_expr()">&nbsp;&nbsp;<em>e.g > 10000</em>
</ul>

<p><h3>Message Format</h3>
<p>

<div style="width: 50em">
<textarea name="message_format" cols="100" rows="20">
&lt;&lt;letter_head&gt;&gt;
&lt;&lt;student_details&gt;&gt;
&lt;&lt;fee_balance&gt;&gt;
</textarea>

<p>use <em>&lt;&lt;letter_head&gt;&gt;</em>, <em>&lt;&lt;student_details&gt;&gt;</em> and <em>&lt;&lt;fee_balance&gt;&gt;</em> to refer to the <a href="/images/letterhead2.png">school's letterhead</a>, student's details (e.g name,adm no.,class) and fee balance summary, respectively.
</div>

<table>
<tr>
<td><input type="submit" name="view_print" value="View/Print">
<td><input type="submit" name="download" value="Download as Spreadsheet">
</table>
</form>

</body>

</html>
*;

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

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
			$formatted_num = $sign . $formatted_num;
			$formatted_num .= $cents;
		}

		
	}
	return $formatted_num;

}
