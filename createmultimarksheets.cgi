#!/usr/bin/perl

use strict;
use warnings;
use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my %session;
my $authd = 0;
my $logd_in = 0;

my $con;
my $id;

my $full_user = 0;

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
		#privileges set
		if (exists $session{"privileges"}) {
			my $priv_str = $session{"privileges"};
			my $spc = " ";
			$priv_str =~ s/\+/$spc/g;
			$priv_str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			if ($priv_str eq "all") { 
				$full_user++;
				$authd++;
			}
		}
	}
}


my %auth_params;
my $valid_data_posted = 0;
if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	$valid_data_posted = 1;
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

my $content = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/createmultimarksheets.cgi">Create Multiple Marksheets</a>
	<hr> 
};

my ($classes_seen, $subjects_seen) = (0,0);

if ($authd) {

	my $current_yr = (localtime)[5] + 1900;
	my @errors = ();
	my $feedback = '';

	my $study_years = 0;

	my ($class_err, $subject_err) = ("", "");
	my ($class, $subject);

	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	

	my @subjects = ();
	my @classes = ();
	my $exam = undef;

	my @exams = ();

	if ($con) {

		my $prep_stmt3 = $con->prepare("SELECT id,value FROM vars WHERE id='1-subjects' OR id='1-classes' OR id='1-exam' LIMIT 3");
		if ($prep_stmt3) {
			my $rc = $prep_stmt3->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt3->fetchrow_array()) {
					if ($rslts[0] eq "1-subjects") {
						$subjects_seen++;
						if ($full_user) {
							@subjects = split/,/,$rslts[1];
						}
					}
					elsif ($rslts[0] eq "1-classes") {
						$classes_seen++;
						if ($full_user) {
							@classes = split/,/,$rslts[1];
						}
					}
					elsif ($rslts[0] eq "1-exam") {
						$exam = $rslts[1];
						if ($exam =~ /(\d{4,})/) {
							$current_yr = $1;
						}
						else {
							$exam .= "($current_yr)";
						}
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM  vars statement: ", $prep_stmt3->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt3->errstr, $/;
		}

		#exams
		my $prep_stmt4 = $con->prepare("SELECT DISTINCT exam_name FROM marksheets ORDER BY time DESC");

		if ($prep_stmt4) {

			my $rc = $prep_stmt4->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt4->fetchrow_array()) {
					push @exams, $rslts[0];
				}

			}
			else {
				print STDERR "Could not execute SELECT FROM  marksheets statement: ", $prep_stmt4->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt4->errstr, $/;
		}

	}

	VALID_DATA_POSTED: {
	if ($valid_data_posted) {

		unless ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and ($auth_params{"confirm_code"} eq $session{"confirm_code"}) ) {
			$feedback = qq!<span style="color: red">Your request was not sent with the appropriate tokens.</span> Do not alter any of the hidden values in this HTML form. To refresh your tokens, reload this page.!;
			$valid_data_posted = 0;
			last VALID_DATA_POSTED; 
		}

		unless ( exists $auth_params{"exam_count"} and $auth_params{"exam_count"} =~ /^\d+$/ ) {
			$valid_data_posted = 0;
			$feedback = qq!<span style="color: red">Your request was not sent with valid authentication values.</span> Do not alter any of the hidden values in this HTML form.!;	
			$valid_data_posted = 0;
			last VALID_DATA_POSTED;
		}

		my $exam_count = $auth_params{"exam_count"};
		my @formula_exams = ();

		#check if formula is valid
		#i.e. all exams referenced exists
		if ( exists $auth_params{"formula"} and length($auth_params{"formula"}) > 0 and $exam_count > 0) {

			my $formula = lc($auth_params{"formula"});

			my $seen_exams = 0;
			my $valid_formula = 0;
	
			for my $exam (@exams) {

				my $lc_exam = lc($exam);

				#tried using s///
				#didn't work. perhaps because
				#of metacharacters in exam names
				my $exam_index = index( $formula, $lc_exam );

				if ( $exam_index >= 0 ) {
					my $n_formula = substr($formula, 0, $exam_index) . substr($formula, $exam_index + length($lc_exam));
					$formula = $n_formula;

					push @formula_exams, $lc_exam;

					if ( ++$seen_exams >= $exam_count ) {
						$valid_formula++;
						last;
					
					}
				}

			}

			unless ( $valid_formula ) {
				$feedback = qq!<span style="color: red">One or more of the exams referenced in your formula does not exist.</span> Only select an exam from the list supplied.!;
				$valid_data_posted = 0;
				last VALID_DATA_POSTED;
			}

			unless ($formula =~ m!^[0-9\.\+\-\*\/\s\(\)]+$!) {
				$feedback = qq!<span style="color: red">Invalid formula supplied.</span> Only basic math operators like '(',')','+','-','*' and '/' are supported.!;
				$valid_data_posted = 0;
				last VALID_DATA_POSTED;
			}
		}


		my @selected_classes = ();
		my @selected_subjects = ();

		for my $param (keys %auth_params) {
			#class
			if ( $param =~ /^class_/ ) {
				push @selected_classes, $auth_params{$param};
			}

			if ($param =~ /^subject_/) {
				push @selected_subjects, $auth_params{$param};
			}
		}

		unless (scalar(@selected_classes) > 0) {
			$feedback = qq!<span style="color: red">You did not select any classes to create marksheets for.</span>!;
			$valid_data_posted = 0;
			last VALID_DATA_POSTED;
		}

		unless (scalar(@selected_subjects) > 0) {
			$feedback = qq!<span style="color: red">You did not select any subjects to create marksheets for.</span>!;
			$valid_data_posted = 0;
			last VALID_DATA_POSTED;
		}

		
		#read student_rolls table
		my %student_rolls;

		my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls WHERE grad_year >= ?");
 
		if ($prep_stmt1) {

			my $rc = $prep_stmt1->execute($current_yr);

			if ($rc) {

				while (my @rslts = $prep_stmt1->fetchrow_array()) {

					#pass over the remaining rows to unvoid unfinished errors
					
					my ($table_name,$saved_class,$start_year) = @rslts;
					my $class_yr = ($current_yr - $start_year) + 1;
					$saved_class =~ s/\d+/$class_yr/;
						
					$student_rolls{lc($saved_class)} = $table_name;

				}
			}
			else {
				print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
			}
		}
		else {
			print STDERR "Could not create SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/; 
		}

		#read marksheets table
		my %marksheets = ();
		my %marksheet_table_names = ();

		my @where_clause_bits = ();
		foreach (keys %student_rolls) {
			push @where_clause_bits, "roll=?";
		}
			
		my $where_clause = 'WHERE ' . join(' OR ', @where_clause_bits);

		my $prep_stmt4 = $con->prepare("SELECT table_name,roll,exam_name,subject FROM marksheets $where_clause");

		if ($prep_stmt4) {

			my $rc = $prep_stmt4->execute(values %student_rolls);

			if ($rc) {

				while (my @rslts = $prep_stmt4->fetchrow_array()) {
					$marksheets{lc($rslts[1] . "_" . $rslts[2] . "_" . $rslts[3])} = $rslts[0];
					$marksheet_table_names{$rslts[0]}++;
				}

			}
			else {
				print STDERR "Could not execute SELECT FROM marksheets: ", $prep_stmt4->errstr, $/;
			}

		}
		else {
			print STDERR "Could not prepare SELECT FROM marksheets: ", $prep_stmt4->errstr, $/;
		}

		my $formula = 0;
		if ( scalar(@formula_exams) > 0 ) {
			$formula = lc($auth_params{"formula"});
		}

		my @log_actions = ();
		my $time = time;

		my $cntr = 0;

		for my $class (@selected_classes) {

			next unless (exists $student_rolls{lc($class)});

			my $roll = $student_rolls{lc($class)};

			my %list_students = ();

			#get list of students
			my $prep_stmt5 = $con->prepare("SELECT adm,subjects FROM `$roll`");

			if ($prep_stmt5) {

				my $rc = $prep_stmt5->execute();

				if ($rc) {
					while (my @rslts = $prep_stmt5->fetchrow_array()) {
						my @subjs = split/,/,$rslts[1];

						for my $subj (@subjs) {
							$list_students{lc($subj)}->{$rslts[0]}++;
						}
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM adms: ", $prep_stmt5->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM adms: ", $prep_stmt5->errstr, $/;  
			}




			for my $subject (@selected_subjects) {

				#some students should be taking this subject
				next unless (scalar(keys %{$list_students{lc($subject)}}) > 0);

				#create table
				#my %student_records = ();
				#my %assoc_marksheets = ();
				if (not exists $marksheets{ lc($roll . "_" . $exam . "_" . $subject)} ) {

					#print "X-Debug-0-$cntr: No marksheet $exam($subject)\r\n";
					$cntr++;

					my $possib_t_name = time;

					while (1) {
						$possib_t_name = gen_token(1);
						last if ( not exists $marksheet_table_names{$possib_t_name} );
					}
				
					#create table
					my $rc = $con->do("CREATE TABLE `$possib_t_name` (adm smallint unsigned unique, marks smallint unsigned)");
					unless ($rc) {
						print STDERR "Could not CREATE TABLE: ", $con->errstr, $/;	
					}

					#print "X-Debug-1-$cntr: Create table $possib_t_name\r\n";

					#add to marksheets table	
					my $prep_stmt6 = $con->prepare("INSERT INTO marksheets VALUES(?,?,?,?,?)");

					if ($prep_stmt6) {

						my $rc = $prep_stmt6->execute($possib_t_name,$roll,$exam,$subject,$time);
						if ($rc) {
							#add to action_log
							push @log_actions, "CREATE MARKSHEET ($class $exam $subject)";
						}
						else {
							print STDERR "Could not execute INSERT INTO marksheets statement: ", $prep_stmt6->errstr, $/;
						}
					}
					else {
						print STDERR "Could not create INSERT INTO marksheets statement: ", $prep_stmt6->errstr, $/;
					}

					#read associated marksheets
					my %assoc_marksheets = ();

					if ( scalar(@formula_exams) > 0 ) {

						for my $exam_n (@formula_exams) {

							if ( exists $marksheets{lc($roll . "_" . $exam_n . "_" . $subject)} ) {

								my $marksheet_table = $marksheets{lc($roll . "_" . $exam_n . "_" . $subject)};

								my $prep_stmt8 = $con->prepare("SELECT adm,marks FROM `$marksheet_table`");

								if ($prep_stmt8) {

									my $rc = $prep_stmt8->execute();

									if ($rc) {

										while (my @rslts = $prep_stmt8->fetchrow_array()) {

											my $adm = $rslts[0];
											my $mark = $rslts[1];

											$assoc_marksheets{$adm}->{$exam_n} = $mark;

											#print "X-Debug-$cntr-assoc-$adm: $exam_n -> $mark\r\n";
										}
									}
									else {
										print STDERR "Could not execute SELECT FROM $marksheet_table: ", $prep_stmt8->errstr, $/;
									}
								}
								else {
									print STDERR "Could not prepare SELECT FROM $marksheet_table: ", $prep_stmt8->errstr, $/;  
								}

							}
							else {
								#set value as zero
								for my $adm (%{$list_students{lc($subject)}}) {
									$assoc_marksheets{$adm}->{$exam_n} = 0;
								}
							}
						}
					}

					#process formula
					my %results = ();

					for my $adm ( keys %{$list_students{lc($subject)}} ) {

						my $res = $formula;

						if ( scalar(@formula_exams) > 0 ) {

							for my $exam_n (@formula_exams) {

								my $exam_index = index( $res, $exam_n );

								if ( $exam_index >= 0 ) {

									$res = substr($res, 0, $exam_index) . $assoc_marksheets{$adm}->{$exam_n}. substr($res, $exam_index + length($exam_n));
									#$res = $n_formula;
								}

								#$res =~ s/$exam_n/$assoc_marksheets{$adm}->{$exam_n}/;
							}
						}

						#print "X-Debug-$cntr-$adm: $res\r\n";

						my $result = eval($res);
						#round result
						$result = sprintf("%.0f", $result);

						unless ($result =~ /^\d+$/) {
							$result = 0;
						}

						$results{$adm} = $result; 
						
					}


					#add to marksheet
					my $prep_stmt9 = $con->prepare("INSERT INTO `$possib_t_name` VALUES(?,?)");
					if ($prep_stmt9) {
						for my $adm (keys %results) {
							my $rc = $prep_stmt9->execute($adm, $results{$adm});
							unless ($rc) {
								print STDERR "Could not execute INSERT INTO `$possib_t_name`: ", $prep_stmt9->errstr, $/;  
							}
						}
					}
					else {
						print STDERR "Could not prepare INSERT INTO `$possib_t_name`: ", $prep_stmt9->errstr, $/;  
					}
				}
				#$cntr++;
			}
		}


		#write to log
		my @today = localtime;	
		my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

		open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

    		if ($log_f) {
                	@today = localtime;	
			my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
			flock ($log_f, LOCK_EX) or print STDERR "Could not log create student roll for $id due to flock error: $!$/";
			seek ($log_f, 0, SEEK_END);

			for my $log_action (@log_actions) {
		 		print $log_f "$id $log_action $time\n";
			}

			flock ($log_f, LOCK_UN);
                	close $log_f;
        	}
		else {
			print STDERR "Could not log create student roll for $id: $!\n";
		}

		$con->commit();

		$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Multiple Marksheets</title>
</head>
<body>
$header
<p><em><span style="color: green">Your marksheets have been successfully created!</span></em> You can now <a href="/cgi-bin/editmarksheet.cgi">use the marksheets</a>
</html>
</body>
};

		#$valid_data_posted = 0;
	}

	}

	if (not $valid_data_posted) {

		#subjects
		my @subjs_select = ();
		for my $subj (sort {$a cmp $b} @subjects) {
			push @subjs_select, qq!<INPUT type="checkbox" checked="1" name="subject_$subj" value="$subj"><LABEL for="subject_$subj">$subj</LABEL>!;
		}
		
		my $subjs_select_str = join("<BR>", @subjs_select);


		#classes
		my %grouped_classes = ();

		for my $class (@classes) {
			if ($class =~ /(\d+)/) {
				my $yr = $1;
				$grouped_classes{$yr}->{$class}++;
			}
		}
		my @classes_select = ();

		for my $yr (sort {$a <=> $b} keys %grouped_classes) {

			my @yr_classes = ();
			for my $class (sort {$a cmp $b} keys %{$grouped_classes{$yr}}) {
				push @yr_classes, qq!<INPUT type="checkbox" checked="1" name="class_$class" value="$class"><LABEL for="class_$class">$class</LABEL>!;
			}
			push @classes_select, join("&nbsp;&nbsp;", @yr_classes);
		}
	
		my $classes_select_str = join("<BR>", @classes_select);

		my $exams_select = "";

		for my $exam (@exams) {
			$exams_select .= qq!<INPUT type="checkbox" onclick="add('$exam')" id="$exam">$exam<BR>!;
		}

	 	my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Multiple Marksheets</title>

<SCRIPT type="text/javascript">

var selected = [];

function add(exam_name) {

	if (document.getElementById(exam_name).checked) {
		selected.push(exam_name);
	}
	else {
		for (var i = 0; i < selected.length; i++) {
			if (selected[i] === exam_name) {
				selected.splice(i, 1);
				break;
			}
		}
	}
	
	if (selected.length > 0) {
		document.getElementById("formula").readOnly = false;
	}
	else {
		document.getElementById("formula").readOnly = true;
	}

	if (selected.length > 1) {
		var ratio = 1 / selected.length;
		var txt_bts = [];
		for (var j = 0; j < selected.length; j++) {
			txt_bts.push(ratio.toString() + " * " + selected[j]);
		}
		var txt = txt_bts.join(" + ");
		document.getElementById("formula").value = txt; 
	}
	else {
		document.getElementById("formula").value = exam_name;	
	}

	document.getElementById("exam_count").value = selected.length;
}

</SCRIPT>

</head>
<body>
$header
$feedback
<FORM method="POST" action="/cgi-bin/createmultimarksheets.cgi">
<input type="hidden" name="confirm_code" value="$conf_code">
<input type="hidden" name="exam_count" id="exam_count" value="0"> 
<table cellpadding="2%">
<tr><th><label for="exam">Exam</label><td><input type="text" disabled value="$exam" name="exam" size="30">
<hr>
<tr><th><label>Subjects</label><td>$subjs_select_str
<hr>
<tr><th><label>Classes</label><td>$classes_select_str
<hr>
<tr><th>Formula<td><em>Which exams would you like to use?</em><br><div style="height: 150px; overflow: scroll">$exams_select</div><br><INPUT type="text" readonly="1" name="formula" id="formula" value="0" size="90">
<hr>
<tr><td><input type="submit" name="create_multiple_marksheets" value="Create">
</table>
</FORM>
</html>
</body>
};

	}

}
else {

	if ($logd_in) {

		$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Multiple Marksheets</title>
</head>
<body>
$header
<em>Sorry. You are not authorized to create multiple marksheets.<br><br>Only administrator accounts can perform this action.</em>
</body>
</html>	
};
	}

	#user not logged in, send them to
	#the login page
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/createmultimarksheets.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href=\"/login.html?cont=/cgi-bin/createmultimarksheets.cgi\">/login.html?cont=/cgi-bin/createmultimarksheets.cgi</a>. If you were not, <a href=\"/cgi-bin/createmultimarksheets.cgi\">Click Here</a> 
		</body>
                </html>";

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
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
